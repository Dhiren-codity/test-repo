# frozen_string_literal: true

require 'spec_helper'

# frozen_string_literal: true

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
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end

    it 'returns 400 when content is missing' do
      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'detects language from path and passes it to python service' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'puts 1'))
        .and_return({ 'score' => 80.0, 'issues' => [] })

      post '/analyze', { content: 'puts 1', path: 'lib/test.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['summary']).to be_a(Hash)
    end
  end

  describe 'GET /status' do
    it 'returns aggregated services status with healthy and unreachable states' do
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .and_return({ status: 'healthy' }, { status: 'unreachable', error: 'timeout' })

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['ruby']['status']).to eq('healthy')
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('unreachable')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content or new_content are missing' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new code review for valid input' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
        .and_return({ 'changes' => [{ 'line' => 1, 'type' => 'add' }] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'b'))
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to eq({ 'changes' => [{ 'line' => 1, 'type' => 'add' }] })
      expect(json_response['new_code_review']).to eq({ 'score' => 90, 'issues' => [] })
    end

    it 'falls back to params when JSON is invalid' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'changes' => [] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 75, 'issues' => [] })

      post '/diff?old_content=old&new_content=new', 'not-json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to eq({ 'changes' => [] })
      expect(json_response['new_code_review']).to eq({ 'score' => 75, 'issues' => [] })
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'returns metrics, review, and computed overall_quality' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'code'))
        .and_return({ 'complexity' => 2 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code'))
        .and_return({ 'score' => 90, 'issues' => ['one'] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['metrics']).to eq({ 'complexity' => 2 })
      expect(json_response['review']).to eq({ 'score' => 90, 'issues' => ['one'] })
      expect(json_response['overall_quality']).to eq(20.0)
    end

    it 'returns overall_quality 0.0 when a service returns an error' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'error' => 'down' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 100, 'issues' => [] })

      post '/metrics', { content: 'anything' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['overall_quality']).to eq(0.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end

    it 'returns aggregated statistics and health score' do
      file_stats = {
        'total_files' => 4,
        'total_lines' => 1000,
        'languages' => { 'ruby' => 2, 'python' => 2 }
      }
      review_stats = {
        'average_score' => 80.0,
        'total_issues' => 6,
        'average_complexity' => 0.5
      }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: array_including))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: array_including))
        .and_return(review_stats)

      post '/dashboard', { files: [{ path: 'a.rb', content: 'puts 1' }, { path: 'b.py', content: 'print()' }] }.to_json,
           'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)

      expect(json_response).to have_key('timestamp')
      expect(json_response['file_statistics']).to eq(file_stats)
      expect(json_response['review_statistics']).to eq(review_stats)
      expect(json_response['summary']['total_files']).to eq(4)
      expect(json_response['summary']['total_lines']).to eq(1000)
      expect(json_response['summary']['languages']).to eq({ 'ruby' => 2, 'python' => 2 })
      expect(json_response['summary']['average_quality_score']).to eq(80.0)
      expect(json_response['summary']['total_issues']).to eq(6)
      expect(json_response['summary']['health_score']).to eq(62.0)
    end

    it 'returns health_score 0.0 when a service returns an error' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'error' => 'down' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'average_score' => 90.0, 'total_issues' => 0, 'average_complexity' => 0.0 })

      post '/dashboard', { files: [{ path: 'a', content: 'x' }] }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['summary']['health_score']).to eq(0.0)
    end
  end
end
