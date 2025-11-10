# frozen_string_literal: true

require_relative '../app/polyglot_api'

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

  describe 'POST /analyze validations' do
    it 'passes correlation id to downstream services' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(:content, :path), kind_of(String))
        .and_return({ 'language' => 'ruby', 'lines' => ["puts 'hi'"] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content, language: 'ruby'), kind_of(String))
        .and_return({ 'score' => 90.0, 'issues' => [] })

      post '/analyze', { content: "puts 'hi'", path: 'app.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to be_a(String)
      expect(body['summary']['language']).to eq('ruby')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when params are missing' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new review on success' do
      old_content = "puts 'old'"
      new_content = "puts 'new'"

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', { old_content: old_content, new_content: new_content })
        .and_return({ 'changes' => [{ 'line' => 1, 'type' => 'modified' }] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', { content: new_content })
        .and_return({ 'score' => 88.5, 'issues' => [] })

      post '/diff', { old_content: old_content, new_content: new_content }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']['changes']).to be_an(Array)
      expect(json_response['new_code_review']['score']).to eq(88.5)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array missing' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end
  end

  describe 'Validation errors store endpoints' do
    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)
      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Validation errors cleared')
    end
  end

  describe 'private helpers' do
    let(:instance) { PolyglotAPI.new }

    describe '#detect_language' do
      it 'detects known language by extension' do
        expect(instance.send(:detect_language, 'foo.rb')).to eq('ruby')
        expect(instance.send(:detect_language, 'bar.py')).to eq('python')
        expect(instance.send(:detect_language, 'main.go')).to eq('go')
      end

      it 'returns unknown for unrecognized extension' do
        expect(instance.send(:detect_language, 'README.txt')).to eq('unknown')
      end
    end

    describe '#calculate_quality_score' do
      it 'returns 0.0 when metrics has error' do
        metrics = { 'error' => 'boom' }
        review = { 'score' => 90, 'issues' => [] }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(0.0)
      end

      it 'returns 0.0 when review has error' do
        metrics = { 'complexity' => 1 }
        review = { 'error' => 'boom' }
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(0.0)
      end

      it 'clamps score between 0 and 100' do
        expect(instance.send(:calculate_quality_score, { 'complexity' => 0 },
                             { 'score' => 120, 'issues' => [] })).to eq(100)
        expect(instance.send(:calculate_quality_score, { 'complexity' => 5 },
                             { 'score' => 10, 'issues' => Array.new(10) })).to eq(0)
      end

      it 'computes expected score' do
        metrics = { 'complexity' => 1 }
        review = { 'score' => 85, 'issues' => ['n1'] }
        # 85/100 = 0.85; penalties: 0.1 + 0.5 = 0.6 -> 0.25 * 100 = 25.0
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(25.0)
      end
    end

    describe '#calculate_dashboard_health_score' do
      it 'returns 0.0 when input has errors' do
        file_stats = { 'error' => 'oops' }
        review_stats = { 'average_score' => 90 }
        expect(instance.send(:calculate_dashboard_health_score, file_stats, review_stats)).to eq(0.0)
      end

      it 'clamps health score at lower bound' do
        file_stats = { 'total_files' => 5 }
        review_stats = { 'average_score' => 10,
                         'total_issues' => 100, 'average_complexity' => 3 }
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats)).to eq(0.0)
      end

      it 'computes expected health score' do
        file_stats = { 'total_files' => 5 }
        review_stats = { 'average_score' => 90.0,
                         'total_issues' => 10, 'average_complexity' => 0.5 }
        # 90 - (10/5*2) - (0.5*30) = 90 - 4 - 15 = 71
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats)).to eq(71.0)
      end
    end
  end
end