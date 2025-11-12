RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |v| v }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end

    it 'returns 422 with validation errors' do
      error_obj = double('ValidationError', to_hash: { field: 'content', message: 'is required' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_obj])
      post '/analyze', { path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Validation failed')
      expect(json_response['details']).to be_an(Array)
      expect(json_response['details'].first).to include('field' => 'content')
    end

    it 'passes detected language to python service and forwards correlation id' do
      corr_id = 'abc-123'
      header 'HTTP_X_CORRELATION_ID', corr_id
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |v| v }

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'puts 1', path: 'file.ts'), corr_id)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'puts 1', language: 'typescript'), corr_id)
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/analyze', { content: 'puts 1', path: 'file.ts' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['correlation_id']).to eq(corr_id)
    end

    it 'falls back to params when JSON body is invalid' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |v| v }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 80, 'issues' => [] })

      post '/analyze?content=puts+1&path=test.rb', 'not-json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['summary']).to include('language' => 'ruby')
    end
  end

  describe 'GET /status' do
    it 'reports status for all services' do
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8080/health', hash_including(timeout: 2))
        .and_return(double(code: 200))
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8081/health', hash_including(timeout: 2))
        .and_return(double(code: 200))

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']).to include('ruby', 'go', 'python')
      expect(json['services']['go']['status']).to eq('healthy')
      expect(json['services']['python']['status']).to eq('healthy')
    end

    it 'handles unhealthy and unreachable services' do
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8080/health', hash_including(timeout: 2))
        .and_return(double(code: 500))
      allow(HTTParty).to receive(:get)
        .with('http://localhost:8081/health', hash_including(timeout: 2))
        .and_raise(StandardError.new('connection refused'))

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']['go']['status']).to eq('unhealthy')
      expect(json['services']['python']['status']).to eq('unreachable')
      expect(json['services']['python']).to have_key('error')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when required params are missing' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to match(/Missing/)
    end

    it 'returns diff and new code review' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
        .and_return({ 'changes' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'b'))
        .and_return({ 'score' => 88, 'issues' => [] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['diff']).to include('changes' => 1)
      expect(json['new_code_review']).to include('score' => 88)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end

    it 'returns metrics, review and overall_quality' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'code'))
        .and_return({ 'complexity' => 0, 'other' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code'))
        .and_return({ 'score' => 90, 'issues' => [{}, {}] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']).to include('complexity' => 0)
      expect(json['review']).to include('score' => 90)
      expect(json['overall_quality']).to eq(0)
    end

    it 'gracefully handles upstream errors and sets overall_quality to 0' do
      allow(HTTParty).to receive(:post)
        .with('http://localhost:8080/metrics', hash_including(timeout: 5))
        .and_raise(StandardError.new('boom'))
      allow(HTTParty).to receive(:post)
        .with('http://localhost:8081/review', hash_including(timeout: 5))
        .and_return(double(body: { score: 70, issues: [] }.to_json))

      post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']).to include('error' => 'boom')
      expect(json['overall_quality']).to eq(0.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array missing' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing files array')
    end

    it 'returns aggregated statistics and summary' do
      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }]
      file_stats = {
        'total_files' => 2,
        'total_lines' => 10,
        'languages' => { 'ruby' => 2 }
      }
      review_stats = {
        'average_score' => 80,
        'total_issues' => 4,
        'average_complexity' => 1.0
      }
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files))
        .and_return(review_stats)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json).to have_key('timestamp')
      expect(json['file_statistics']).to include('total_files' => 2)
      expect(json['review_statistics']).to include('average_score' => 80)
      expect(json['summary']).to include('health_score' => 46.0)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces' do
      traces = [{ 'correlation_id' => 'a', 'path' => '/x' }, { 'correlation_id' => 'b', 'path' => '/y' }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_traces']).to eq(2)
      expect(json['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return([])

      get '/traces/xyz'
      expect(last_response.status).to eq(404)
      json = JSON.parse(last_response.body)
      expect(json['error']).to match(/No traces/)
    end

    it 'returns traces for the given correlation id' do
      traces = [{ 'path' => '/a' }, { 'path' => '/b' }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return(traces)

      get '/traces/abc'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['correlation_id']).to eq('abc')
      expect(json['trace_count']).to eq(2)
      expect(json['traces']).to eq(traces)
    end
  end

  describe 'Validation errors endpoints' do
    it 'GET /validation/errors returns stored errors' do
      errors = [{ 'field' => 'content', 'message' => 'invalid' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_errors']).to eq(1)
      expect(json['errors']).to eq(errors)
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)
      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['message']).to eq('Validation errors cleared')
    end
  end
end
